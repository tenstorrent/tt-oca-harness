# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP address-map register sweep test (PyUVM).

Intention: prove the CPU-LSU can decode sep_cpu_ctrl and one safe CSR in every
LSU-reachable CSR block (including ABR and the entropy pool), and that the
interior reserved span inside sep_cpu_ctrl completes (does not hang) and is
not a live alias of the neighbouring registers. Not a full dead-space walk.

Bring-up holds the CPU off. Expected offsets/resets/masks come from
env/sep_reg_meta.py and the ABR / pool seq constants — see sep_address_map_seq.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL
from seq_lib.sep_address_map_seq import CPU_CTRL_INTERIOR_HOLES, sep_address_map_seq
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_OKAY = 0
MASK32 = 0xFFFF_FFFF


@pyuvm.test()
class sep_address_map_test(sep_base_test):
    """Register sweep of sep_cpu_ctrl over the CPU LSU bus."""

    # Every graded contract this leaf owns. Dropping any one of them is the
    # failure mode a clean exit would otherwise hide.
    required_evidence = (
        "CHK-REFCNT-READ",
        "CHK-BASEADDR-RW",
        "CHK-RW-READBACK",
        "CHK-FABRIC-WALK",
        "CHK-CPU-CTRL-HOLE",
    )
    min_evidence = 5

    async def _access(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        wdata: int = 0,
    ) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(
            f"cpu_ctrl_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=4,
            size=2,
        )
        await self.start_seq(seq)
        return seq

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

        # 0x158-0x177 owns no register: sep_cpu_ctrl.rdl places
        # SEP_FUSE_SENSE_STATUS at 0x150 and SEP_SW_DEBUG at 0x178 and declares
        # nothing between. memory_map.adoc states the contract for an offset
        # inside a unit's allocated extent that owns no register: the unit
        # accepts it, reads return zero and writes are discarded, both OKAY.
        # That is the graded expectation here.
        #
        # The same passage says such an offset cannot alias a live register
        # because register decode is an exact address match rather than a range
        # -- not because the access is refused. So the alias check is the second
        # half of the contract, not a consolation for not grading the response.
        sw_addr = SEP_CPU_CTRL.addr("SEP_SW_DEBUG")

        # Positive control for the alias check. SEP_SW_DEBUG is `sw = rw`
        # (sep_cpu_ctrl.rdl), so a write must move it; without proving that, "the
        # neighbour did not change after a hole write" also holds when the write
        # path is dead. SEP_FUSE_SENSE_STATUS is not usable as a control here --
        # it is `sw = r`, so no AXI write can ever change it.
        sw_restore = (await self._access(SepAxiOp.READ, sw_addr)).rdata & MASK32
        probe = sw_restore ^ 0xA5A5_5A5A
        await self._access(SepAxiOp.WRITE, sw_addr, wdata=probe)
        sw_live = (await self._access(SepAxiOp.READ, sw_addr)).rdata & MASK32
        assert sw_live == probe, (
            f"CHK-CPU-CTRL-HOLE FAIL: control write to SEP_SW_DEBUG 0x{sw_addr:08x} "
            f"read back 0x{sw_live:08x}, expected 0x{probe:08x} -- the write path is "
            "dead, so the no-alias check below would hold for the wrong reason"
        )

        hole_ok = 0
        for addr in CPU_CTRL_INTERIOR_HOLES:
            hole = await self._access(SepAxiOp.READ, addr)
            assert not hole.timed_out, (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} timed out; whatever the "
                "response ought to be, the access has to retire"
            )
            assert hole.resp_code == RESP_OKAY, (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} resp={hole.resp_code}, "
                "expected OKAY -- memory_map.adoc says a unit accepts an offset "
                "inside its extent that owns no register"
            )
            got = hole.rdata & MASK32
            assert got == 0, (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} data=0x{got:08x}, expected zero"
            )
            hole_ok += 1

        # A hole write must not land on the live neighbour, whose value is now the
        # probe the control above proved writable.
        named = CPU_CTRL_INTERIOR_HOLES[1]
        wr = await self._access(SepAxiOp.WRITE, named, wdata=0xFFFF_FFFF)
        assert not wr.timed_out, f"CHK-CPU-CTRL-HOLE FAIL: write 0x{named:08x} timed out"
        assert wr.resp_code == RESP_OKAY, (
            f"CHK-CPU-CTRL-HOLE FAIL: write 0x{named:08x} resp={wr.resp_code}, "
            "expected OKAY -- memory_map.adoc says a unit accepts an offset "
            "inside its extent that owns no register"
        )
        sw_after = (await self._access(SepAxiOp.READ, sw_addr)).rdata & MASK32
        assert sw_after == probe, (
            f"CHK-CPU-CTRL-HOLE FAIL: write 0x{named:08x} changed SEP_SW_DEBUG "
            f"0x{probe:08x}->0x{sw_after:08x}; the hole aliases a live register"
        )
        await self._access(SepAxiOp.WRITE, sw_addr, wdata=sw_restore)

        self.logger.info(
            "CHK-CPU-CTRL-HOLE PASS: %d hole word(s) read OKAY with zero, "
            "the hole write retired OKAY, and none aliases SEP_SW_DEBUG "
            "(control write proved it writable)",
            hole_ok,
        )
