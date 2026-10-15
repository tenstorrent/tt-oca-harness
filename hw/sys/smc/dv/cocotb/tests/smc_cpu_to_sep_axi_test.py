# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU-control CSR path precheck."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpu_to_sep_axi_test_seq import smc_cpu_to_sep_axi_test_seq
from seq_lib.smc_cpu_vip_utils import check_cpu_bfm_observability
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
# Composition (smc_cpu_to_sep_axi_test_seq, directed, no polling):
#   5 CPU_CTRL reset-default reads (CPU_CTRL_READS)
# + 2 scratch write/readback (csr_write_readback)
# + 2 restore write/readback (csr_restore)
CPU_TO_SEP_MIN_CSR_ACCESSES = 9


@pyuvm.test()
class smc_cpu_to_sep_axi_test(smc_base_test):
    """Run the CPU-control to SEP-facing CSR reachability precheck."""

    required_evidence = ("CHK-CPU-BFM-OBSERVABILITY",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_to_sep_axi_test_seq("cpu_to_sep_axi_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_bfm_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CPU_TO_SEP_MIN_CSR_ACCESSES,
            # Not measured on this path: `SmcCsrSeq.timeouts` counts only the
            # tolerated no-responses of `csr_read_bounded` / `csr_short_timeout`
            # (seq_lib/smc_csr_seq_utils.py), which this sequence never calls.
            # Every access is bounded by the driver's `cfg.axi_timeout_ns`,
            # which raises on expiry.
            timeouts=None,
            proxy=False,
            details="SEP_IN AXI master-BFM CPU-control to SEP-facing path checked",
        )
