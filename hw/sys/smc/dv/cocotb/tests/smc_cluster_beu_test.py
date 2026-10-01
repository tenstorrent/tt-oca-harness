# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN reads and writes at the documented BEU window answer DECERR at the reset aperture."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_addr_map import CLOCK_GATE_CONTROL_RESET
from seq_lib.smc_cluster_beu_test_seq import smc_cluster_beu_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cluster_beu_test(smc_base_test):
    """BEU addresses outside the reset apertures answer DECERR and change nothing.

    No access in this testcase reaches a Bus Error Unit; see the sequence
    docstring for what is proven instead.
    """

    required_evidence = ("CHK-BEU-WINDOW-DECERR",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cluster_beu_test_seq("smc_cluster_beu_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Byte golden: CLOCK_GATE_CONTROL's reset word composed from the generated
        # RDL field symbols against what it held after every BEU access.
        assert len(seq.refused) == 5, f"{len(seq.refused)} of 5 BEU addresses checked"
        assert seq.restored_word is not None, "CLOCK_GATE_CONTROL was not read back"
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: a read and a write at each of the five BEU
            # addresses, then six reset reads. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=16,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            expected_bytes=(CLOCK_GATE_CONTROL_RESET & 0xFFFF_FFFF).to_bytes(4, "big"),
            observed_bytes=seq.restored_word.to_bytes(4, "big"),
            details=(
                f"{len(seq.refused)} documented BEU addresses answered DECERR on a read and "
                f"a write at the REGION_SIZE reset, and the registers sharing their low "
                f"address bits kept their generated resets. No BEU property is covered by "
                f"this testcase."
            ),
        )
