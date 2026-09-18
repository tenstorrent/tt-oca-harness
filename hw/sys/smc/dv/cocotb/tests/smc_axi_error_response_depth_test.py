# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS AXI error response depth bounded test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_addr_map import CLOCK_GATE_CONTROL_RESET
from seq_lib.smc_axi_error_response_depth_test_seq import (
    ALIVE_SENTINEL,
    ERROR_PROBES,
    smc_axi_error_response_depth_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axi_error_response_depth_test(smc_base_test):
    """Run bounded invalid-address probes plus recovery read."""

    required_evidence = ("CHK-AXI-ERR-DEPTH",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_axi_error_response_depth_test_seq("axi_error_response_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Byte golden. `expected_bytes` is CLOCK_GATE_CONTROL's reset word
        # composed from the generated RDL field symbols; `observed_bytes` is the
        # word the DUT returned on the alive sentinel. The scoreboard compares
        # them (env/smc_scoreboard.py:861-867), so this record carries a
        # fail-capable, DUT-sensitive payload rather than resting on
        # `csr_accesses >= min_csr_accesses`, which is `5 >= 5` on every run --
        # `seq.accesses` is the sequence's own counter and
        # `assert_all_reachable` already pinned it to exactly that number.
        assert seq.sentinel_word is not None, "sequence recorded no sentinel word"
        await self.record_protocol_vip(
            SmcProtocolVipKind.AXI,
            type(self).__name__,
            # Directed stimulus floor: 3 ERROR_PROBES + the 2 alive-sentinel
            # CSR reads that bracket them. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=len(ERROR_PROBES) + 2,
            csr_accesses=seq.accesses,
            # `timeouts` is left unmeasured (prints `n/a`): this path issues no
            # bounded read, so `seq.timeouts` is structurally 0 and reporting it
            # would manufacture a clean-looking statistic.
            proxy=False,
            expected_bytes=CLOCK_GATE_CONTROL_RESET.to_bytes(4, "big"),
            observed_bytes=seq.sentinel_word.to_bytes(4, "big"),
            details=(
                "Invalid-address AXI error responses and recovery read checked "
                f"(error_responses={seq.error_responses}, sentinel "
                f"0x{ALIVE_SENTINEL:08x}=0x{seq.sentinel_word:08x})"
            ),
        )
