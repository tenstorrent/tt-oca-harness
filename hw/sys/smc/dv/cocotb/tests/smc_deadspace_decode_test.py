# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS deadspace-decode test: offsets past a block's decoded extent are refused."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_deadspace_decode_test_seq import smc_deadspace_decode_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_deadspace_decode_test(smc_base_test):
    """Probe wrap-period offsets past PeakRDL SIZE and watch live CSRs."""

    required_evidence = (
        "CHK-DEADSPACE-BYSTANDER",
        "CHK-DEADSPACE-READ-REFUSED",
        "CHK-DEADSPACE-SEED",
        "CHK-DEADSPACE-SWEEP",
        "CHK-DEADSPACE-WRITE-REFUSED",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_deadspace_decode_test_seq("deadspace_decode_seq")
        await self.start_seq(seq, self.env.sep_in_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.AXI,
            type(self).__name__,
            # Directed stimulus floor: 5 unconditional accesses per probe
            # (live read, seed write, seed readback, dead read, restore write)
            # for each of the 9 DeadspaceProbe entries; the dead-write legs are
            # conditional on the dead read completing. Literal here, not read
            # from `seq.accesses`.
            min_csr_accesses=45,
            csr_accesses=seq.accesses,
            # Not measured on this path, so `n/a` rather than a clean-looking
            # 0: every access goes through `_xfer` (`allow_timeout = False`) or
            # `csr_read`, and `SmcCsrSeq.timeouts` is bumped only by
            # `csr_read_bounded` / `csr_short_timeout`, which this sequence
            # never calls. Printing `seq.timeouts` would advertise a statistic
            # that is structurally 0. Timeout discipline is carried by the
            # driver, which raises on a no-response.
            timeouts=None,
            proxy=False,
            details=(
                "Deadspace probes past the decoded extent "
                f"(wrap={len(seq.wrap_to_live)} alias={len(seq.read_alias)} "
                f"accepted={len(seq.accepted_dead)} refused={len(seq.refused)} "
                f"read_refused={len(seq.read_refused)})"
            ),
        )
