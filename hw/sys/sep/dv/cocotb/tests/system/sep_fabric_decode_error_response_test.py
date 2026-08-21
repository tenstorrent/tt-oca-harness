# SPDX-License-Identifier: Apache-2.0
"""SEP fabric decode-error / negative-response test (PyUVM).

The CPU-LSU AXI master (no_cpu splice; the bare-sep primary
stimulus path, no inbound filter) accesses an UNMAPPED local address and gets the
EXACT decode-error response (DECERR per fabric/port_table.adoc), while a
known-mapped CSR on the SAME bus returns OKAY + its reset value -- proving the
SEP local xbar error-slave path, not a wedge.

reference refs: sep_cpu_lsu_negative_matrix_test,
sep_cpu_ifu_invalid_target_test,
sep_fabric_xbar_error_closure_test.
Mapping: COVERED_STRONGER. the reference suite accepts any non-OKAY (a 50us timeout is tolerated
as "blocked"); this OSS port asserts the EXACT DECERR with allow_timeout=False, so
a wedged/undecoded-but-non-responding bus FAILs instead of passing as "blocked".

Accepted delta: kept SEPARATE from the owner-frozen sep_address_map_test
(which walks mapped apertures expecting OKAY only) for negative-path failure
isolation. The IFU invalid-target half of the reference suite uses the dedicated
CPU IFU ROM master, which is not separately brought out on the bare-sep no_cpu
build; the LSU decode path proves the same xbar error-slave contract.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_fabric_decode_error_seq import (
    MAPPED_CSR_ADDR,
    RESP_DECERR,
    RESP_OKAY,
    SepFabricDecErrCfg,
    SepFabricMappedReadSeq,
    SepFabricUnmappedProbeSeq,
    SepFabricUnmappedWriteProbeSeq,
)


@pyuvm.test()
class sep_fabric_decode_error_response_test(sep_base_test):
    """Unmapped local address -> DECERR; mapped CSR -> OKAY, on one CPU-LSU bus.

    RANDOMIZED: which unmapped local addresses are probed (reference suite-proven anchors +
    reserved-gap addresses) and which gets the write probe vary per seed
    (SepFabricDecErrCfg). The mapped-CSR anchor and the DECERR/OKAY contract are fixed.
    """

    async def run_scenario(self) -> None:
        self.cfg_fab = SepFabricDecErrCfg(self.random_seed())
        self.logger.info("decode-error config: %s", self.cfg_fab.summary())
        await self.bring_up_no_cpu()

        # CHK-OKAY: a known-mapped CSR returns OKAY + the expected value (the
        # scoreboard value-checks via item.expected; here we also assert the
        # response code). Proves the CPU-LSU bus is live and decoding.
        mapped = SepFabricMappedReadSeq()
        await self.start_seq(mapped)
        assert mapped.resp_code == RESP_OKAY, (
            f"mapped CSR 0x{MAPPED_CSR_ADDR:08x} returned resp={mapped.resp_code}, "
            f"expected OKAY={RESP_OKAY}"
        )
        self.logger.info(
            "CHK-OKAY PASS: mapped CSR 0x%08x -> OKAY, rdata=0x%08x",
            MAPPED_CSR_ADDR, mapped.rdata,
        )

        # CHK-DECERR: each unmapped local address returns EXACTLY DECERR on the read
        # (AR/R) path. Arm the s_axi monitor for the intentional DECERR (a DECERR on
        # the CPU-LSU bus is otherwise a real decode bug); allow_timeout=False makes
        # a wedge FAIL.
        for addr in self.cfg_fab.unmapped_reads:
            self.env.axi_monitor.arm_expected_decerr(1)
            probe = SepFabricUnmappedProbeSeq(addr)
            await self.start_seq(probe)
            assert probe.resp_code == RESP_DECERR, (
                f"unmapped read 0x{addr:08x} returned resp={probe.resp_code}, "
                f"expected DECERR={RESP_DECERR} (not SLVERR/timeout/OKAY)"
            )
            self.logger.info(
                "CHK-DECERR PASS: unmapped read 0x%08x -> DECERR (resp=%d)",
                addr, probe.resp_code,
            )

        # CHK-DECERR-WR: an unmapped WRITE returns DECERR on the B-channel -- the
        # write decode (AW/W/B) is a distinct datapath from the read probes above.
        self.env.axi_monitor.arm_expected_decerr(1)
        waddr = self.cfg_fab.unmapped_write
        wprobe = SepFabricUnmappedWriteProbeSeq(waddr)
        await self.start_seq(wprobe)
        assert not wprobe.timed_out, (
            f"unmapped write 0x{waddr:08x} did not complete (wedge); expected a DECERR response"
        )
        assert wprobe.resp_code == RESP_DECERR, (
            f"unmapped write 0x{waddr:08x} returned resp={wprobe.resp_code}, "
            f"expected DECERR={RESP_DECERR} (B-channel)"
        )
        self.logger.info(
            "CHK-DECERR-WR PASS: unmapped write 0x%08x -> DECERR (resp=%d, B-channel)",
            waddr, wprobe.resp_code,
        )

        # CHK-NONVAC: the mapped(OKAY) + unmapped(DECERR) accesses on the SAME bus
        # prove the checker is not always-true -- a wedged bus would fail the OKAY
        # half and an always-DECERR fabric would fail it too; an always-OKAY decode
        # would fail the DECERR half. The armed-monitor tally confirms every expected
        # DECERR beat actually appeared on the raw pins, independent of the master.
        expected_decerr = len(self.cfg_fab.unmapped_reads) + 1   # reads + the one write
        assert self.env.axi_monitor.expected_decerr_seen == expected_decerr, (
            f"s_axi monitor saw {self.env.axi_monitor.expected_decerr_seen} expected "
            f"DECERR beats, expected {expected_decerr}"
        )
        self.logger.info(
            "CHK-NONVAC PASS: same s_axi bus returned OKAY (mapped) and DECERR "
            "(%d unmapped reads + 1 unmapped write, monitor-confirmed on raw pins)",
            len(self.cfg_fab.unmapped_reads),
        )
