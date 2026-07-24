# SPDX-License-Identifier: Apache-2.0
"""Local-fabric CSR depth sweep over real SEP_IN AXI."""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

# Local-fabric CSR windows backed by real register blocks. Expected values are
# RDL reset constants (identical on Verilator and VCS) -> G3 spec-anchored,
# EXCEPT MAILBOX0_OUT_STATUS (see note). Each read verifies decode + route AND
# the reset value, not merely an OKAY response.
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

# The I3C CSR windows are currently stubbed in RTL (smc_peripherals instantiates
# i3ccore_stub -- "TODO: stub i3c out until the updated open-source controller is
# integrated") and complete every access with SLVERR/0xBADCAB1E. They are swept
# error-tolerantly so this test still proves the fabric decodes/routes to the I3C
# window (no hang) without asserting a real value the stub cannot provide.
LOCAL_FABRIC_STUBBED_READS = [
    ("I3C0_HCI_VERSION", 0xC003_A000, None),
    ("I3C0_HC_CAPABILITIES", 0xC003_A00C, None),
]


class smc_local_fabric_csr_depth_test_seq(SmcCsrSeq):
    """Sample representative local-fabric CSR windows with one AXI ingress."""

    def __init__(self, name: str = "smc_local_fabric_csr_depth_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(LOCAL_FABRIC_READS)
        await self.csr_read_many_allow_error(LOCAL_FABRIC_STUBBED_READS)
        total = len(LOCAL_FABRIC_READS) + len(LOCAL_FABRIC_STUBBED_READS)
        assert self.accesses == total, "local fabric CSR sweep mismatch"
