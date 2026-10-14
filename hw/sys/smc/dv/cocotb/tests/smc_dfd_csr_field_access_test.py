# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DST field storage, scratch registers and same-offset block independence.

Sources: dfd_dst.rdl, dfd_dst_sink.rdl, dfd_funnel.rdl, hw/ip/dfd/regs/smc_cla.rdl.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dfd_csr_field_access_test_seq import smc_dfd_csr_field_access_test_seq
from smc_base_test import smc_base_test

# Lower bound on the SEP_IN accesses of one pass of the sequence.
CSR_FIELD_ACCESS_MIN_CSR_ACCESSES = 800


@pyuvm.test()
class smc_dfd_csr_field_access_test(smc_base_test):
    """Write patterns into DST fields and scratch registers and prove storage and isolation."""

    required_evidence = (
        "CHK-DST-RW-PATTERNS",
        "CHK-DST-FIELD-ISOLATION",
        "CHK-DST-UNDEFINED-BITS",
        "CHK-DST-INST-FIELDS-RW",
        "CHK-SCRATCH-PATTERNS",
        "CHK-SCRATCH-NO-ALIAS",
        "CHK-APERTURE-OFFSET-ISOLATION",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_csr_field_access_test_seq("csr_field_access_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CSR_FIELD_ACCESS_MIN_CSR_ACCESSES,
            proxy=False,
            details=f"{seq.accesses} accesses, {seq.value_checks} value compares",
        )
