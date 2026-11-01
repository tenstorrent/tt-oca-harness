# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The CPU-LSU decodes every LSU-reachable CSR block, and sep_cpu_ctrl holes read 0 without alias.

Intention: prove the CPU-LSU can decode sep_cpu_ctrl and one safe CSR in every
LSU-reachable CSR block (including ABR and the entropy pool), and that the
interior reserved span inside sep_cpu_ctrl completes (does not hang) and is
not a live alias of the neighbouring registers. Not a full dead-space walk.

Bring-up holds the CPU off. Expected offsets/resets/masks come from
env/sep_reg_meta.py and the ABR / pool seq constants; see sep_address_map_seq.
The eFuse-shim window boundary must select the shim port for its first word and
leave SEP on the next word (CHK-EXT-DEMUX-BOUND); the PR-EXT tap shows that
next word's read on the extension port (CTRL-EXT-DEMUX-PORT) and no read of
the first word there (CTRL-EXT-DEMUX-SHIM). The PR-OUT tap shows that no
fabric-walk read leaves on the outbound port, and that a read of an SMU-aperture
word behind an enabled outbound filter pair, in the same tap window after the
walk, puts exactly one AR at that address on the port (CTRL-FABRIC-WALK-LOCAL).
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_fabric_tap import SepFabricTap
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_address_map_seq import (
    CPU_CTRL_INTERIOR_HOLES,
    FABRIC_BLOCKS,
    sep_address_map_seq,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_filter_bank_seq import SMU_PAGE, SMU_PAGE_WORD, SepFilterBank

RESP_OKAY = 0
RESP_DECERR = 3
MASK32 = 0xFFFF_FFFF
# Rows of FABRIC_BLOCKS: one CSR in each LSU-reachable block that the
# sep_address_map_seq docstring lists.
FABRIC_WALK_ROWS = 22
# Outbound filter entries opened over the SMU page for the PR-OUT liveness read.
OUT_PAIR = (0, 1)

# Generated SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP window. An unmapped address
# in the remainder of that external aperture answers DECERR (AXI decode).
EFUSE_SHIM_BASE = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_BASE_ADDR")
EFUSE_SHIM_SIZE = sym("SEP_EXTERNAL_EFUSE_SHIM_CTRL_REG_MAP_SIZE")


@pyuvm.test()
class sep_address_map_test(sep_base_test):
    """sep_cpu_ctrl CSRs write back, holes read 0 without alias, and the shim boundary holds."""

    # Every graded contract this leaf owns. Dropping any one of them is the
    # failure mode a clean exit would otherwise hide.
    required_evidence = (
        "CHK-CPU-CTRL-RESET",
        "CHK-REFCNT-READ",
        "CHK-BASEADDR-RW",
        "CHK-RW-READBACK",
        "CHK-FABRIC-WALK",
        "CHK-CPU-CTRL-HOLE",
        "CHK-EXT-DEMUX-BOUND",
    )
    min_evidence = 7

    async def _access(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        wdata: int = 0,
        expect_error: bool = False,
    ) -> SepAxiAccessSeq:
        seq = SepAxiAccessSeq(
            f"cpu_ctrl_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=4,
            size=2,
            expect_error=expect_error,
        )
        await self.start_seq(seq)
        return seq

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        outf = SepFilterBank(self, "out")
        await outf.program_pair(OUT_PAIR, SMU_PAGE, SMU_PAGE + 0xFFF)
        seq = sep_address_map_seq("addr_map_seq", out_probe=SMU_PAGE_WORD)
        await self.start_seq(seq)
        for idx in OUT_PAIR:
            await outf.restore_reset(idx)
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
        wrong = [f"{n}=0x{got:08x}/0x{exp:08x}" for n, exp, got in seq.reset_reads if got != exp]
        assert seq.reset_reads and not wrong, (
            f"CHK-CPU-CTRL-RESET FAIL: {len(seq.reset_reads)} reset read(s), "
            f"mismatch (got/exp) {wrong}"
        )
        self.logger.info(
            "CHK-CPU-CTRL-RESET PASS: regs=%d each equals its RDL reset value",
            len(seq.reset_reads),
        )
        self.logger.info(
            "CHK-REFCNT-READ PASS: REFERENCE_COUNTER readable and advancing, last read 0x%08x_%08x",
            seq.ref_counter_high,
            seq.ref_counter_low,
        )
        self.logger.info(
            "CHK-BASEADDR-RW PASS: %d SEP base/size CSR(s) write->readback->restore",
            seq.base_addr_rw_checks,
        )
        self.logger.info(
            "CHK-RW-READBACK PASS: %d pure-RW CSR(s) write->masked readback->restore->readback%s",
            seq.write_readback_checks,
            (
                f" ({len(seq.write_readback_storage_only)} of them storage-only -- RDL "
                f"`reserved` placeholders with no software-usable fields: "
                f"{', '.join(seq.write_readback_storage_only)})"
            )
            if seq.write_readback_storage_only
            else "",
        )
        walk_ars = seq.fabric_walk_out_ars
        probe_ars = seq.out_probe_ars
        walk = (
            f"rows={len(seq.fabric_walk_rows)} pr_out_ar={len(walk_ars)} "
            f"[{' '.join(b.fmt() for b in walk_ars)}] "
            f"live_addr=0x{SMU_PAGE_WORD:x} live_ar={len(probe_ars)} "
            f"[{' '.join(b.fmt() for b in probe_ars)}]"
        )
        # Same text as SepChkLog.ctrl(): a read that leaves on the outbound port
        # is answered OKAY by the bench responder, so CHK-FABRIC-WALK needs no
        # walk read on PR-OUT. The liveness read in the same window must show its
        # one AR there, so an absence cannot come from a tap that records nothing.
        if walk_ars or len(probe_ars) != 1 or probe_ars[0].addr != SMU_PAGE_WORD:
            self.logger.error("CTRL-MISSING FABRIC-WALK-LOCAL: %s", walk)
            raise AssertionError(f"CTRL-MISSING FABRIC-WALK-LOCAL: {walk}")
        self.logger.info("CTRL-FABRIC-WALK-LOCAL seen: %s", walk)
        # The scoreboard grades the response of every row and the value of a row
        # with an expectation; the gate above stops the leaf on any error. This
        # check requires that every row was read and answered OKAY, so a shorter
        # walk fails.
        planned = [name for name, _addr, _exp in FABRIC_BLOCKS]
        walked = [name for name, _ok in seq.fabric_walk_rows]
        not_ok = [name for name, ok in seq.fabric_walk_rows if not ok]
        rows = (
            f"rows={len(walked)} planned={len(planned)} expected={FABRIC_WALK_ROWS} "
            f"not_okay={not_ok} missing={[n for n in planned if n not in walked]}"
        )
        assert len(planned) == FABRIC_WALK_ROWS and walked == planned and not not_ok, (
            f"CHK-FABRIC-WALK FAIL: {rows}"
        )
        self.logger.info(
            "CHK-FABRIC-WALK PASS: rows=%d of %d, each LSU-reachable block CSR read and "
            "answered OKAY",
            len(walked),
            FABRIC_WALK_ROWS,
        )

        # 0x158-0x177 owns no register: sep_cpu_ctrl.rdl places
        # SEP_FUSE_SENSE_STATUS at 0x150 and SEP_SW_DEBUG at 0x178 and declares
        # nothing between. memory_map.adoc states the contract for an offset
        # inside a unit's allocated extent that owns no register: the unit
        # accepts it, reads return zero and writes are discarded, both OKAY.
        # That is the graded expectation here.
        #
        # The same passage says such an offset cannot alias a live register:
        # register decode is an exact address match rather than a range, so the
        # alias check is the second half of the contract.
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

        # CHK-EXT-DEMUX-BOUND. ext_demux_decode() in sep.sv is Tenstorrent-owned
        # decode on an adopter-owned aperture: the first word selects the eFuse
        # shim port and the next word answers DECERR. The two responses must
        # differ. CTRL-EXT-DEMUX-PORT shows on the PR-EXT tap that the next word
        # leaves SEP on the extension port and that the port answers it DECERR.
        # The value behind the shim is adopter owned and is not graded.
        off = EFUSE_SHIM_BASE + EFUSE_SHIM_SIZE
        ext = SepFabricTap("PR-EXT").start()
        ext_rsp = SepFabricTap("PR-EXT-RSP").start()
        ext_mark, rsp_mark = ext.mark(), ext_rsp.mark()
        # Keyed off the response rather than the monitor tally: the monitor
        # counts on its own clock edge, which may not have run when start_seq
        # returns, and a standing credit would absorb the next unexpected DECERR
        # anywhere on this bus.
        mon = self.env.axi_monitor
        mon.arm_expected_decerr(1)
        past = await self._access(SepAxiOp.READ, off, expect_error=True)
        if past.timed_out or past.resp_code != RESP_DECERR:
            mon.release_expected_decerr(1)
        assert not past.timed_out, (
            f"CHK-EXT-DEMUX-BOUND FAIL: read 0x{off:08x} timed out; the external "
            f"port must be terminated, not left to hang"
        )
        assert past.resp_code == RESP_DECERR, (
            f"CHK-EXT-DEMUX-BOUND FAIL: read 0x{off:08x} resp={past.resp_code}, "
            f"expected DECERR (3) one word past the shim window"
        )
        ars = ext.since(ext_mark, "ar")
        rs = ext_rsp.since(rsp_mark, "r")
        port = (
            f"addr=0x{off:08x} ar=[{' '.join(b.fmt() for b in ars)}] "
            f"r=[{' '.join(b.fmt() for b in rs)}]"
        )
        # Same text as SepChkLog.ctrl(): CHK-EXT-DEMUX-BOUND reads its DECERR as
        # the extension port's answer, so a read that never reached the port, or
        # a port reply other than one DECERR beat to that request, fails the leaf.
        if not (
            len(ars) == 1
            and ars[0].addr == off
            and ars[0].id is not None
            and len(rs) == 1
            and rs[0].resp == RESP_DECERR
            and rs[0].id == ars[0].id
            and rs[0].last == 1
        ):
            self.logger.error("CTRL-MISSING EXT-DEMUX-PORT: %s", port)
            raise AssertionError(f"CTRL-MISSING EXT-DEMUX-PORT: {port}")
        self.logger.info("CTRL-EXT-DEMUX-PORT seen: %s", port)

        shim_mark = ext.mark()
        inside = await self._access(SepAxiOp.READ, EFUSE_SHIM_BASE)
        shim_ars = ext.since(shim_mark, "ar")
        await ext.stop()
        await ext_rsp.stop()
        shim = (
            f"addr=0x{EFUSE_SHIM_BASE:08x} ext_ar={len(shim_ars)} "
            f"[{' '.join(b.fmt() for b in shim_ars)}]"
        )
        # Same text as SepChkLog.ctrl(): memory_map.adoc sends the shim window to
        # the eFuse controller rather than out the extension port, so
        # CHK-EXT-DEMUX-BOUND needs that read to put no AR on PR-EXT.
        if shim_ars:
            self.logger.error("CTRL-MISSING EXT-DEMUX-SHIM: %s", shim)
            raise AssertionError(f"CTRL-MISSING EXT-DEMUX-SHIM: {shim}")
        self.logger.info("CTRL-EXT-DEMUX-SHIM seen: %s", shim)
        assert not inside.timed_out, (
            f"CHK-EXT-DEMUX-BOUND FAIL: read 0x{EFUSE_SHIM_BASE:08x} timed out"
        )
        assert inside.resp_code != RESP_DECERR, (
            f"CHK-EXT-DEMUX-BOUND FAIL: read 0x{EFUSE_SHIM_BASE:08x} also answered "
            f"DECERR, so the shim port was never selected and the decode boundary "
            f"is not proven -- both addresses took the external path"
        )
        self.logger.info(
            "CHK-EXT-DEMUX-BOUND PASS: 0x%08x selected the shim port (resp=%d) "
            "and 0x%08x answered DECERR on the extension port; the %d-byte "
            "window boundary is graded, the adopter value is not",
            EFUSE_SHIM_BASE,
            inside.resp_code,
            off,
            EFUSE_SHIM_SIZE,
        )
