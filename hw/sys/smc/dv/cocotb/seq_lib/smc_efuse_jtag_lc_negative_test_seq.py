# SPDX-License-Identifier: Apache-2.0
"""eFuse JTAG lifecycle-gating observable-subset sequence.

The full SMC eFuse JTAG access-control policy lives in
``hw/smc/smc_peripherals/efuse/smc_efuse_wrapper.sv``. It gates the
*JTAG-side* AXI-Lite port (``axil_smc_otp_jtag_req_i``) by the decoded SMC
lifecycle state:

  * writes and non-identity reads are blocked (routed to
    ``prim_axi_lite_err_slv`` -> SLVERR, data ``0xBADCAB1E``) in
    PROD (``lc_state == 0x1``) and RMA_SIP (``0x2`` / ``0x3``);
  * CHIPLET_ID / PACKAGE_ID reads stay allowed in every state; and
  * a lifecycle differential-decode integrity error blocks everything.

Exercising that matrix needs an ``lc_state_i`` drive hook plus a JTAG-side
AXI-Lite master. The current SMC OSS ``tb_top`` only exposes the SEP_IN CSR
path (``smc u_dut`` leaves ``lc_state_i`` / the JTAG eFuse port unconnected),
so the full matrix is tracked as P2-15.

This sequence covers the subset reachable today over SEP_IN CSR:
  * read ``CHIP_CONFIG_LC_STATE`` to record the effective lifecycle state, and
  * read the always-allowed identity registers ``CHIPLET_ID`` / ``PACKAGE_ID``
    (the exact registers the RTL policy keeps readable in PROD / RMA_SIP).
"""

from __future__ import annotations

from .smc_csr_seq_utils import SmcCsrSeq

CHIP_CONFIG_LC_STATE = 0xC000_290C
# SEP_IN CSR-mapped SMC_EFUSE_MAP identity registers (smc_top_reg.svh):
#   SMC_EFUSE_MAP_CHIPLET_ID_REG_ADDR = 0xC000_B008
#   SMC_EFUSE_MAP_PACKAGE_ID_REG_ADDR = 0xC000_B028
SMC_EFUSE_MAP_CHIPLET_ID = 0xC000_B008
SMC_EFUSE_MAP_PACKAGE_ID = 0xC000_B028


class smc_efuse_jtag_lc_negative_test_seq(SmcCsrSeq):
    """CSR-observable subset of the eFuse JTAG lifecycle-gating policy."""

    def __init__(self, name: str = "smc_efuse_jtag_lc_negative_test_seq") -> None:
        super().__init__(name)
        self.lc_state = 0

    async def body(self) -> None:
        # CHIP_CONFIG_LC_STATE is a known-readable RO mirror; record the state.
        self.lc_state = await self.csr_read("CHIP_CONFIG_LC_STATE", CHIP_CONFIG_LC_STATE)
        # Identity registers the RTL policy keeps readable in every lifecycle
        # state; bounded because the eFuse-map window may no-decode on a stub.
        await self.csr_read_bounded("SMC_EFUSE_MAP_CHIPLET_ID", SMC_EFUSE_MAP_CHIPLET_ID)
        await self.csr_read_bounded("SMC_EFUSE_MAP_PACKAGE_ID", SMC_EFUSE_MAP_PACKAGE_ID)
        assert self.accesses == 3, "eFuse JTAG LC observable-subset mismatch"
