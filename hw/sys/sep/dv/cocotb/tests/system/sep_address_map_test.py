# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP address-map register sweep test (PyUVM).

Intention: prove the CPU-LSU can decode sep_cpu_ctrl and one safe CSR in every
LSU-reachable CSR block (including ABR and the entropy pool), and that the
interior reserved span inside sep_cpu_ctrl completes with an error response
rather than hanging. Not a full dead-space walk.

Bring-up holds the CPU off. Expected offsets/resets/masks come from
env/sep_reg_meta.py and the ABR / pool seq constants — see sep_address_map_seq.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_address_map_seq import CPU_CTRL_INTERIOR_HOLES, sep_address_map_seq
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_SLVERR = 2
RESP_DECERR = 3


@pyuvm.test()
class sep_address_map_test(sep_base_test):
    """Register sweep of sep_cpu_ctrl over the CPU LSU bus."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_address_map_seq("addr_map_seq")
        await self.start_seq(seq)
        # The scoreboard accumulates response/value errors and defers its raise
        # to check_phase. Without this gate every CHK-* PASS line below prints
        # on a run that has already failed, and a PASS token in a kept log must
        # not survive a failure. The counters below are accesses issued, so
        # they are only evidence once the scoreboard is clean.
        sb_errors = self.env.scoreboard.errors
        assert not sb_errors, (
            f"CHK-ADDRMAP FAIL: {len(sb_errors)} scoreboard error(s) before "
            f"the PASS summary; first: {sb_errors[0]}"
        )
        self.logger.info(
            "CHK-REFCNT-READ PASS: REFERENCE_COUNTER readable as 0x%08x_%08x",
            seq.ref_counter_high,
            seq.ref_counter_low,
        )
        self.logger.info(
            "CHK-BASEADDR-RW PASS: %d SEP base/size CSR(s) write->readback->restore",
            seq.base_addr_rw_checks,
        )
        self.logger.info(
            "CHK-RW-READBACK PASS: %d pure-RW CSR(s) write->masked readback->restore%s",
            seq.write_readback_checks,
            (
                f" ({len(seq.write_readback_storage_only)} of them storage-only -- RDL "
                f"`reserved` placeholders with no software-usable fields: "
                f"{', '.join(seq.write_readback_storage_only)})"
            )
            if seq.write_readback_storage_only
            else "",
        )
        self.logger.info(
            "CHK-FABRIC-WALK PASS: %d LSU-reachable block CSR(s) decoded",
            seq.fabric_walk_checks,
        )
        hole_ok = 0
        for addr in CPU_CTRL_INTERIOR_HOLES:
            self.env.axi_monitor.arm_expected_decerr(1)
            hole = SepAxiAccessSeq(
                f"cpu_ctrl_hole_0x{addr:08x}",
                op=SepAxiOp.READ,
                addr=addr,
                length=4,
                size=2,
                expect_error=True,
            )
            await self.start_seq(hole)
            if hole.timed_out or hole.resp_code != RESP_DECERR:
                self.env.axi_monitor.release_expected_decerr(1)
            assert not hole.timed_out, (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} timed out; the "
                "reserved span must complete with SLVERR or DECERR"
            )
            assert hole.resp_code in (RESP_SLVERR, RESP_DECERR), (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} resp={hole.resp_code}, "
                "expected SLVERR or DECERR"
            )
            hole_ok += 1
        self.logger.info(
            "CHK-CPU-CTRL-HOLE PASS: %d reserved sep_cpu_ctrl word(s) refused "
            "with SLVERR/DECERR (not a timeout)",
            hole_ok,
        )
