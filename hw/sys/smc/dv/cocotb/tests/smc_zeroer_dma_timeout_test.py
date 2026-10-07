# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS zeroer datapath payload test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_dma_timeout_test_seq import smc_zeroer_dma_timeout_test_seq
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
# Composition (smc_zeroer_dma_timeout_test_seq, directed, no polling):
#   6 output-fabric pass-all filter CSR writes
# + ZEROER_CTRL_DEST_ADDR + ZEROER_CTRL_SIZE + ZEROER_CTRL_STATUS trigger
# + 1 ZEROER_CTRL_STATUS readback (S4: armed INT_EN, STATUS masked)
# + S5 busy-lifecycle control: ZEROER_CTRL_SIZE re-arm + ZEROER_CTRL_STATUS
#   trigger + at least one busy poll read + at least one clear poll read. The
#   two polls are bounded loops whose length is data-dependent, so only their
#   guaranteed first iteration is counted here -- this stays a floor, never an
#   equality.
ZEROER_DMA_MIN_CSR_ACCESSES = 14

# JTAG-AXI fabric beats this scenario issues (2 poison preloads + 4 readbacks).
ZEROER_DMA_MIN_FABRIC_ACCESSES = 6


@pyuvm.test()
class smc_zeroer_dma_timeout_test(smc_base_test):
    """Run zeroer over output-fabric payload bytes and check the model."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-ZEROER-CMD-READBACK",
        "CHK-ZEROER-CTRL-STATUS",
        "CHK-ZEROER-REGION-DECODE",
        "CHK-ZEROER-REGION-ZEROED",
        "CHK-ZEROER-STATUS-BUSY-ASSERTED",
        "CHK-ZEROER-STATUS-LIFECYCLE",
        "CHK-ZEROER-TRIGGER-STARTS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_dma_timeout_test_seq("zeroer_dma_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=ZEROER_DMA_MIN_CSR_ACCESSES,
            # Not measured on this path, so `n/a` rather than a clean-looking 0.
            # `SmcCsrSeq.timeouts` is bumped only by `csr_read_bounded` /
            # `csr_short_timeout` (seq_lib/smc_csr_seq_utils.py); this sequence
            # calls neither, so `seq.timeouts` is structurally 0 and printing it
            # would advertise a statistic never taken ([NO-DUMMY-DEAD-CODE]).
            # The sequence's own bounded wait (`_wait_for_zeroer_write`) raises
            # on expiry, so [TIMEOUT-MUST-FAIL] is carried there, not by this
            # field.
            timeouts=None,
            # The framework measures JTAG-AXI beats unconditionally and prints
            # them; without a floor the scoreboard's fabric assert is `6 >= 0`,
            # constant-true -- the same unmeasured-zero shape `timeouts=None`
            # above exists to prevent, one field over.
            # 6 = 2 poison preloads (payload + neighbour) + 4 readbacks
            # (payload, neighbour, and the two S5 lifecycle reads are CSR, not
            # fabric): a literal floor, not derived from the sequence.
            min_fabric_accesses=ZEROER_DMA_MIN_FABRIC_ACCESSES,
            fabric_access_label="jtag_axi_accesses",
            proxy=False,
            details=(
                "Zeroer cleared output-fabric payload via JTAG AXI readback "
                f"(checked_bytes={seq.checked_bytes}; neighbour poison unchanged)"
            ),
        )
