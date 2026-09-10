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


@pyuvm.test()
class sep_address_map_test(sep_base_test):
    """Register sweep of sep_cpu_ctrl over the CPU LSU bus."""

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

        # The generated sep_cpu_ctrl PeakRDL block ties decoded_err and wr_err
        # off, so an interior reserved word completes OKAY with zero data. The
        # xbar still claims the window: a hang is the fail, and a live alias
        # of SEP_FUSE_SENSE_STATUS or SEP_SW_DEBUG is the other fail.
        fuse_addr = SEP_CPU_CTRL.addr("SEP_FUSE_SENSE_STATUS")
        sw_addr = SEP_CPU_CTRL.addr("SEP_SW_DEBUG")
        fuse_before = await self._access(SepAxiOp.READ, fuse_addr)
        sw_before = await self._access(SepAxiOp.READ, sw_addr)
        assert not fuse_before.timed_out and fuse_before.resp_code == RESP_OKAY
        assert not sw_before.timed_out and sw_before.resp_code == RESP_OKAY

        hole_ok = 0
        for addr in CPU_CTRL_INTERIOR_HOLES:
            hole = await self._access(SepAxiOp.READ, addr)
            assert not hole.timed_out, (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} timed out; the "
                "reserved span must complete"
            )
            assert hole.resp_code == RESP_OKAY, (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} resp={hole.resp_code}, "
                "generated PeakRDL grants OKAY"
            )
            got = hole.rdata & 0xFFFF_FFFF
            assert got == 0, (
                f"CHK-CPU-CTRL-HOLE FAIL: read 0x{addr:08x} data=0x{got:08x}; "
                "a reserved word must not hand back a live value"
            )
            hole_ok += 1

        named = CPU_CTRL_INTERIOR_HOLES[1]
        wr = await self._access(SepAxiOp.WRITE, named, wdata=0xFFFF_FFFF)
        assert not wr.timed_out, (
            f"CHK-CPU-CTRL-HOLE FAIL: write 0x{named:08x} timed out"
        )
        fuse_after = await self._access(SepAxiOp.READ, fuse_addr)
        sw_after = await self._access(SepAxiOp.READ, sw_addr)
        assert (fuse_after.rdata & 0xFFFF_FFFF) == (fuse_before.rdata & 0xFFFF_FFFF), (
            f"CHK-CPU-CTRL-HOLE FAIL: write 0x{named:08x} changed "
            f"SEP_FUSE_SENSE_STATUS 0x{fuse_before.rdata:08x}->0x{fuse_after.rdata:08x}"
        )
        assert (sw_after.rdata & 0xFFFF_FFFF) == (sw_before.rdata & 0xFFFF_FFFF), (
            f"CHK-CPU-CTRL-HOLE FAIL: write 0x{named:08x} changed "
            f"SEP_SW_DEBUG 0x{sw_before.rdata:08x}->0x{sw_after.rdata:08x}"
        )
        self.logger.info(
            "CHK-CPU-CTRL-HOLE PASS: %d reserved sep_cpu_ctrl word(s) completed "
            "OKAY with data 0 (not a hang, not a live alias); write 0x%08x left "
            "SEP_FUSE_SENSE_STATUS and SEP_SW_DEBUG unchanged",
            hole_ok,
            named,
        )
