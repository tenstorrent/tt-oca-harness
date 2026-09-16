# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS sideband CSR smoke."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_sideband_protocol_smoke_test_seq import (
    smc_sideband_protocol_smoke_test_seq,
)
from smc_base_test import smc_base_test

# Fail-capable stimulus floor for the SIDEBAND record, written out here rather
# than imported from the sequence's own SIDEBAND_TOTAL_ACCESSES: a floor derived
# from the sequence would shrink together with a sequence that silently stopped
# issuing accesses, which is exactly the failure this floor exists to catch.
# Composition (smc_sideband_protocol_smoke_test_seq):
#   2 x AVS_DEBUG_READBACK (non-destructive-mirror re-read pair)
# + 4 AVS_INTERRUPT reads (entry / after the debug pair / after the
#   pointer-advancing AVS_READBACK / after the write-1-clear)
# + 1 AVS_INTERRUPT_CLEAR write
# + 3 OKAY status reads (AVS_NORMAL_STATUS, AVS_SLAVE_STATUS, AVS_FIFOS_STATUS)
# + 1 AVS_READBACK empty-FIFO read (error response + rdata == 0)
SIDEBAND_MIN_CSR_ACCESSES = 11


@pyuvm.test()
class smc_sideband_protocol_smoke_test(smc_base_test):
    """Run the AVSBus sideband CSR representative precheck."""

    required_evidence = (
        "CHK-AVS-DEBUG-READBACK-NONDESTRUCTIVE",
        "CHK-AVS-FIFOS-STATUS",
        "CHK-AVS-INTERRUPT-MASK",
        "CHK-AVS-INTERRUPT-W1C",
        "CHK-AVS-NORMAL-STATUS",
        "CHK-AVS-READBACK-EMPTY-FIFO-READ",
        "CHK-AVS-READBACK-POINTER-ADVANCE",
        "CHK-AVS-SLAVE-STATUS",
    )
    min_evidence = 8

    # No AUTO-COVERAGE-STAMP: this scenario records its own protocol VIP item
    # from measured counts below, so the base-test activity stamp would only add
    # a second, weaker record of the same traffic.
    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sideband_protocol_smoke_test_seq("sideband_protocol_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=seq.accesses,
            # No timeout statistic is published: every access in this sequence
            # leaves `allow_timeout` False, so the driver raises on expiry and
            # `seq.timeouts` can only ever be 0 here. Reporting that structural
            # zero would advertise a measurement that was never taken.
            timeouts=None,
            min_csr_accesses=SIDEBAND_MIN_CSR_ACCESSES,
            details=(
                f"{seq.accesses} SEP_IN AXI accesses to the AVSBus sideband CSR "
                "window. AVS_DEBUG_READBACK non-destructiveness proven against "
                "its contrast: AVS_INTERRUPT == 0 across the debug re-read pair, "
                "then the pointer-advancing AVS_READBACK read raised exactly "
                "READBACK_UNDERFLOW_INT (avsbus_controller.rdl:299-303) and the "
                "documented write-1-clear returned it to 0. AVS_NORMAL_STATUS / "
                "AVS_SLAVE_STATUS / AVS_FIFOS_STATUS value-compared against "
                "exact idle words built from the generated avsbus_controller.h "
                "field masks -- AVS_SLAVE_STATUS and AVS_FIFOS_STATUS from RDL "
                "field resets, AVS_NORMAL_STATUS from the RDL field "
                "descriptions of the idle state (rdl:188,214: CMD_FIFO_EMPTY and "
                "AVS_BUS_IS_IDLE are hw=w status bits whose RDL resets are 0). "
                "AVS_READBACK asserted to return an error response with "
                "rdata == 0 (rdata == 0 per memmap.adoc:95; the error response "
                "is this integration's empty-readback termination, not a "
                "document-cited property)"
            ),
        )
