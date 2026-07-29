# SPDX-License-Identifier: Apache-2.0
"""Local-fabric CSR depth sweep over real SEP_IN AXI."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Local-fabric CSR windows backed by real register blocks. Expected values are
# RDL reset constants (identical on Verilator and VCS) -> G3 spec-anchored,
# EXCEPT MAILBOX0_OUT_STATUS (see note). Each read verifies decode + route AND
# the reset value, not merely an OKAY response.
# I3C HCI windows are covered by smc_i3c_to_fabric_test at 0xC000_5000 (not the
# stale 0xC003_A000 catalog hole used by removed bare-smc DV-macro tests).
LOCAL_FABRIC_READS = [
    ("SMC_BASE_CONFIG_GLOBAL_BASE", 0xC001_0000, 0x4000_0000),  # was mislabelled RESET_VECTOR_0
    ("CLOCK_GATE_CONTROL", 0xC001_0018, 0x1F00_0000),  # offset 0x18 (was 0x30 before HANG_DET_* added)
    # REGRESSION-LOCK: RDL `empty` reset=0x0; 0x1 is the FIFO-empty flag wire at
    # reset (observed HW behaviour, not a spec reset). [audit: F1 common-mode]
    ("MAILBOX0_OUT_STATUS", 0xC001_8010, 0x1),
    ("ALIAS0_START", 0xC001_2000, 0x0),
    ("ALIAS0_ATTRS", 0xC001_2010, 0x0),
    ("OUTBOUND0_FILTER_CONFIG", 0xC001_6000, 0x0000_3000),
    ("OUTBOUND0_START", 0xC001_6008, 0x0),
    ("UART0_LOG_CTRL", 0xC000_A000, 0x0),
    ("UART0_LSR", 0xC000_A114, 0x0000_0060),
    ("LOG_ENGINE0_CTRL", 0xC000_A200, 0x0),
    ("ZEROER_DEST_ADDR", 0xC003_8200, 0x0),
    ("ZEROER_SIZE", 0xC003_8208, 0x0),
]


class smc_local_fabric_csr_depth_test_seq(SmcCsrSeq):
    """Sample representative local-fabric CSR windows with one AXI ingress."""

    def __init__(self, name: str = "smc_local_fabric_csr_depth_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(LOCAL_FABRIC_READS)
        assert self.accesses == len(LOCAL_FABRIC_READS), "local fabric CSR sweep mismatch"
